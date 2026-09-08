variable "aws_region" {
  type        = string
  description = "AWS region for the VM."
}

variable "instance_type" {
  type        = string
  description = "EC2 instance type mapped from requested vCPU/RAM."
}

variable "vm_name" {
  type        = string
  description = "Name tag for the instance."
  default     = "zammad-requested-vm"
}

variable "allowed_instance_types" {
  type        = list(string)
  description = "Hard cap so a ticket cannot request an arbitrary size."
  default     = ["t3.small", "t3.medium", "t3.large"]
}
