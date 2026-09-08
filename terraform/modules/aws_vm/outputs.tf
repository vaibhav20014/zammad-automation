output "instance_id" {
  value = aws_instance.vm.id
}

output "instance_type" {
  value = aws_instance.vm.instance_type
}

output "private_ip" {
  value = aws_instance.vm.private_ip
}
