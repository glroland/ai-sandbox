#!/bin/bash

oc process vllm-multinode-runtime-template -n redhat-ods-applications | oc apply -n models -f -

