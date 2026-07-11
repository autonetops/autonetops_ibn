variable "project_id" {
  type = string
}

variable "network_name" {
  type    = string
  default = "ibn-platform"
}

variable "subnets" {
  description = "region => CIDR"
  type        = map(string)
}
