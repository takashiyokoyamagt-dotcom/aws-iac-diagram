output "security_group_id" {
  value = aws_security_group.this.id
}

output "service_name" {
  value = aws_ecs_service.this.name
}
