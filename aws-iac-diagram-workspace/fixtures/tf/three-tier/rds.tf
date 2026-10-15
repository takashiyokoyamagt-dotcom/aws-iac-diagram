resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.database[*].id

  tags = {
    Name = local.name
  }
}

resource "aws_db_instance" "main" {
  identifier                  = "${local.name}-db"
  engine                      = "postgres"
  engine_version              = "17.9"
  instance_class              = local.env.db_instance_class
  allocated_storage           = 20
  storage_encrypted           = true
  db_name                     = "app"
  username                    = "app_admin"
  manage_master_user_password = true
  db_subnet_group_name        = aws_db_subnet_group.main.name
  vpc_security_group_ids      = [aws_security_group.db.id]
  multi_az                    = local.env.db_multi_az
  skip_final_snapshot         = var.environment != "prod"
  final_snapshot_identifier   = var.environment == "prod" ? "${local.name}-db-final" : null
}
