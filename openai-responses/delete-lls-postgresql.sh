#!/bin/bash

oc delete deploymentconfig lls-postgresql
oc delete pvc lls-postgresql
oc delete service lls-postgresql
oc delete secret lls-postgresql

