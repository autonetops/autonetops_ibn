# Pin all three in each environment's tfvars after the first successful
# lab deploy; never track "latest".

variable "infrahub_chart_version" {
  type = string
}

variable "prefect_chart_version" {
  type = string
}

variable "kube_prometheus_stack_version" {
  type = string
}
