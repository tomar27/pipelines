# Copyright 2021 The Kubeflow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging
import time
from os import path
from google_cloud_pipeline_components.proto.gcp_resources_pb2 import GcpResources
from google.protobuf import json_format
from .utils import artifact_util
from .utils import json_util
import requests
import google.auth
import google.auth.transport.requests

_POLLING_INTERVAL_IN_SECONDS = 20


def create_endpoint(
    type,
    project,
    location,
    payload,
    gcp_resources,
    executor_input,
):
    """
  Create endpoint and poll the LongRunningOperator till it reaches a final state.
  """
    api_endpoint = location + '-aiplatform.googleapis.com'
    vertex_uri_prefix = f"https://{api_endpoint}/v1/"
    create_endpoint_url = f"{vertex_uri_prefix}projects/{project}/locations/{location}/endpoints"
    endpoint_spec = json.loads(payload, strict=False)
    create_endpoint_request = {
        # TODO(IronPan) temporarily remove the empty fields from the spec
        'endpoint': json_util.recursive_remove_empty(endpoint_spec)
    }

    # Currently we don't check if operation already exists and continue from there
    # If this is desirable to the user and improves the reliability, we could do the following
    # ```
    # from google.api_core import operations_v1, grpc_helpers
    # channel = grpc_helpers.create_channel(location + '-aiplatform.googleapis.com')
    # api = operations_v1.OperationsClient(channel)
    # current_status = api.get_operation(create_endpoint_lro.operation.name)
    # ```

    creds, _ = google.auth.default()
    creds.refresh(google.auth.transport.requests.Request())
    headers = {
        'Content-type': 'application/json',
        'Authorization': 'Bearer ' + creds.token,
        'User-Agent': 'google-cloud-pipeline-components'
    }
    create_endpoint_lro = requests.post(
        url=create_endpoint_url,
        data=json.dumps(create_endpoint_request),
        headers=headers).json()

    if "error" in create_endpoint_lro and create_endpoint_lro["error"]["code"]:
        raise RuntimeError("Failed to create endpoint. Error: {}".format(
            create_endpoint_lro["error"]))

    create_endpoint_lro_name = create_endpoint_lro['name']
    get_operation_uri = f"{vertex_uri_prefix}{create_endpoint_lro_name}"

    # Write the lro to the gcp_resources output parameter
    long_running_operations = GcpResources()
    long_running_operation = long_running_operations.resources.add()
    long_running_operation.resource_type = "VertexLro"
    long_running_operation.resource_uri = get_operation_uri
    with open(gcp_resources, 'w') as f:
        f.write(json_format.MessageToJson(long_running_operations))

    # Poll the LRO till done
    while (not "done" in create_endpoint_lro) or (not create_endpoint_lro['done']):
        time.sleep(_POLLING_INTERVAL_IN_SECONDS)
        logging.info('Endpoint is creating...')
        creds.refresh(google.auth.transport.requests.Request())
        headers = {
            'Content-type': 'application/json',
            'Authorization': 'Bearer ' + creds.token
        }
        create_endpoint_lro = requests.get(
            f"{vertex_uri_prefix}{create_endpoint_lro_name}",
            headers=headers).json()

    if "error" in create_endpoint_lro and create_endpoint_lro["error"]["code"]:
        raise RuntimeError("Failed to create endpoint. Error: {}".format(
            create_endpoint_lro["error"]))
    else:
        logging.info('Create endpoint complete. %s.', create_endpoint_lro)
        artifact_util.update_output_artifact(
            executor_input, 'endpoint',
            vertex_uri_prefix + create_endpoint_lro['response']['endpoint'])
        return
