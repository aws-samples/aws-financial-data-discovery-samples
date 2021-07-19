#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
* Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
* SPDX-License-Identifier: MIT-0
*
* Permission is hereby granted, free of charge, to any person obtaining a copy of this
* software and associated documentation files (the "Software"), to deal in the Software
* without restriction, including without limitation the rights to use, copy, modify,
* merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
* permit persons to whom the Software is furnished to do so.
*
* THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
* INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
* PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
* HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
* OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
* SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

import os
from typing import Optional, Dict, Any
import json
import urllib.parse

from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext
import boto3
import botocore

logger = Logger()
metrics = Metrics()
s3 = boto3.client("s3")

TAG_KEY_NAME = os.getenv("TAG_KEY_NAME", "Severity")
if not TAG_KEY_NAME:
    raise Exception("No TAG_KEY_NAME environment variable defined")

# objects with a score of SCORE_THRESHOLD or higher will be tagged
try:
    SCORE_THRESHOLD = int(os.getenv("SCORE_THRESHOLD", 3))
except ValueError:
    raise Exception("SCORE_THRESHOLD must be an integer")

try:
    GLACIER_TRANSITION_DAYS = int(os.getenv("GLACIER_TRANSITION_DAYS", 365))
except ValueError:
    raise Exception("GLACIER_TRANSITION_DAYS must be an integer")

try:
    EXPIRE_OBJECTS_DAYS = int(os.getenv("EXPIRE_OBJECTS_DAYS", 1825))
except ValueError:
    raise Exception("EXPIRE_OBJECTS_DAYS must be an integer")


def get_json_object(
    bucket: str, key: str, version_id: str = None
) -> Optional[Dict[str, Any]]:
    """
    Return a parsed JSON object from an S3 bucket
    """
    params = {"Bucket": bucket, "Key": key}
    if version_id:
        params["VersionId"] = version_id

    logger.append_keys(bucket=bucket, key=key, version=version_id)
    logger.debug("Retrieving object")
    try:
        response = s3.get_object(**params)
        data = response["Body"].read().decode("utf-8")
        return json.loads(data)
    except Exception:
        logger.exception("Unable to get object")


def tag_object(value: str, bucket: str, key: str, version_id: str = None) -> None:
    """
    Add a new tag (TAG_KEY_NAME) to an existing S3 object
    """
    params = {
        "Bucket": bucket,
        "Key": key,
        "Tagging": {"TagSet": [{"Key": TAG_KEY_NAME, "Value": str(value)}]},
    }
    if version_id:
        params["VersionId"] = version_id

    logger.append_keys(bucket=bucket, key=key, version=version_id)
    try:
        s3.put_object_tagging(**params)
        logger.debug(f"Successfully added {TAG_KEY_NAME} tag")
    except botocore.exceptions.ClientError:
        logger.exception(f"Unable to add {TAG_KEY_NAME} tag")
        metrics.add_metric(name="TaggingFailed", unit=MetricUnit.Count, value=1)
    else:
        metrics.add_metric(name="TaggingSuccess", unit=MetricUnit.Count, value=1)


def lifecycle_config(bucket: str, key: str) -> None:
    """
    Add a new lifecycle configuration to a bucket
    """
    config = {
        "Rules": [
            {
                "Filter": {"Prefix": key},
                "Status": "Enabled",
                "NoncurrentVersionTransitions": [
                    {
                        "NoncurrentDays": GLACIER_TRANSITION_DAYS,
                        "StorageClass": "GLACIER",
                    },
                ],
                "NoncurrentVersionExpiration": {"NoncurrentDays": EXPIRE_OBJECTS_DAYS},
            },
        ]
    }

    logger.append_keys(bucket=bucket)
    try:
        s3.put_bucket_lifecycle_configuration(
            Bucket=bucket, LifecycleConfiguration=config
        )
        logger.debug(f"Successfully added lifecycle configuration")
    except botocore.exceptions.ClientError:
        logger.exception("Unable to add lifecycle configuration")


def process_record(record: Dict[str, Any]) -> None:
    """
    Process an individual S3 event notification record
    """
    bucket = record.get("s3", {}).get("bucket", {}).get("name")
    key = record.get("s3", {}).get("object", {}).get("key")
    if key:
        key = urllib.parse.unquote_plus(key)

    version_id = record.get("s3", {}).get("object", {}).get("versionId")
    data = get_json_object(bucket, key, version_id)
    if not data:
        logger.warn("No data found in S3 object")
        metrics.add_metric(name="EmptyObject", unit=MetricUnit.Count, value=1)
        return

    detail = data.get("detail", {})
    severity_score = int(detail["severity"]["score"])
    severity_desc = detail["severity"]["description"]
    resourcesAffected = detail.get("resourcesAffected", {})
    if not resourcesAffected:
        logger.warn("No resourcesAffected found in Macie event")
        metrics.add_metric(name="MissingResources", unit=MetricUnit.Count, value=1)
        return

    affected_bucket = resourcesAffected["s3Bucket"]["name"]
    affected_key = resourcesAffected["s3Object"]["key"]
    affected_version = resourcesAffected["s3Object"].get("versionId")

    logger.append_keys(
        bucket=affected_bucket, key=affected_key, version=affected_version
    )

    if severity_score < SCORE_THRESHOLD:
        logger.debug(
            f"{severity_score} ({severity_desc}) < {SCORE_THRESHOLD}, skipping"
        )
        metrics.add_metric(name="TaggingSkipped", unit=MetricUnit.Count, value=1)
        return

    logger.info(
        f"{severity_score} ({severity_desc}) >= {SCORE_THRESHOLD}, adding tag and lifecycle policy"
    )

    tag_object(
        value=severity_desc,
        bucket=affected_bucket,
        key=affected_key,
        version_id=affected_version,
    )

    lifecycle_config(bucket=affected_bucket, key=affected_key)


@metrics.log_metrics(capture_cold_start_metric=True)
@logger.inject_lambda_context(log_event=True)
def handler(event: Dict[str, Any], context: LambdaContext) -> None:
    records = event.get("Records", [])

    logger.info(f"Found {len(records)} records in event")
    for record in records:
        process_record(record)
