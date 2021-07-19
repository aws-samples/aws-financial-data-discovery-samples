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

from typing import Dict, Any, Optional

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
import boto3
import botocore
from crhelper import CfnResource

helper = CfnResource(
    json_logging=False,
    log_level="INFO",
    boto_level="CRITICAL",
    sleep_on_delete=120,
)

try:
    logger = Logger()
    s3 = boto3.client("s3")
except Exception as e:
    helper.init_failure(e)


def put_bucket_notification(bucket: str, config: Dict[str, Any]) -> None:
    """
    Put an S3 bucket notification configuration
    """
    try:
        s3.put_bucket_notification_configuration(
            Bucket=bucket, NotificationConfiguration=config
        )
        logger.debug(f"Successfully put bucket notification to s3://{bucket}")
    except botocore.exceptions.ClientError:
        logger.exception(f"Unable to put bucket notification to s3://{bucket}")
        raise


@helper.create
@helper.update
def create(event: Dict[str, Any], context: LambdaContext) -> Optional[str]:
    props = event.get("ResourceProperties", {})
    bucket_name = props.get("BucketName")
    if not bucket_name:
        raise ValueError("BucketName has not been provided")

    config = props.get("NotificationConfiguration", {})
    if not config:
        raise ValueError("NotificationConfiguration has not been provided")

    put_bucket_notification(bucket=bucket_name, config=config)

    return "ResultsNotifications"


@helper.delete
def delete(event: Dict[str, Any], context: LambdaContext) -> None:
    props = event.get("ResourceProperties", {})
    bucket_name = props.get("BucketName")
    if not bucket_name:
        raise ValueError("BucketName has not been provided")

    # empty dict removes bucket notification
    put_bucket_notification(bucket=bucket_name, config={})


@logger.inject_lambda_context(log_event=True)
def handler(event: Dict[str, Any], context: LambdaContext) -> None:
    helper(event, context)
