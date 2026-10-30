output "instance_id" {
  value = aws_instance.runner.id
}
output "supabase_allow_cidr" {
  value = "${aws_eip.runner.public_ip}/32"
}
output "lifecycle_role_arn" {
  value = aws_iam_role.lifecycle.arn
}
