terraform {
  required_version = ">= 1.3.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

resource "aws_instance" "vm" {
  ami           = data.aws_ami.al2023.id
  instance_type = var.instance_type
  subnet_id     = data.aws_subnets.default.ids[0]

  tags = {
    Name      = var.vm_name
    ManagedBy = "zammad-automation"
    Ticket    = var.vm_name
  }
}
