# three-tier と同じ構成を、公開モジュール（vpc／alb／rds）とローカルモジュール（./modules/ecs-service）で書いたもの。
# 公開モジュールの中身はリポジトリに無い（terraform init しない）。中身は A5 の要約表で展開する前提。

locals {
  name = var.project

  tags = {
    Project = var.project
  }
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 6.7"

  name = local.name
  cidr = var.vpc_cidr
  azs  = var.azs

  public_subnets   = var.public_subnets
  private_subnets  = var.private_subnets
  database_subnets = var.database_subnets

  enable_nat_gateway = true
  single_nat_gateway = true

  create_database_subnet_group       = true
  create_database_subnet_route_table = true

  tags = local.tags
}

module "alb" {
  source  = "terraform-aws-modules/alb/aws"
  version = "~> 10.0"

  name               = "${local.name}-alb"
  load_balancer_type = "application"
  vpc_id             = module.vpc.vpc_id
  subnets            = module.vpc.public_subnets

  enable_deletion_protection = false

  security_group_ingress_rules = {
    all_http = {
      from_port   = 80
      to_port     = 80
      ip_protocol = "tcp"
      cidr_ipv4   = "0.0.0.0/0"
    }
  }
  security_group_egress_rules = {
    all = {
      ip_protocol = "-1"
      cidr_ipv4   = module.vpc.vpc_cidr_block
    }
  }

  listeners = {
    http = {
      port     = 80
      protocol = "HTTP"
      forward = {
        target_group_key = "app"
      }
    }
  }

  target_groups = {
    app = {
      name              = "${local.name}-app"
      protocol          = "HTTP"
      port              = var.app_port
      target_type       = "ip"
      create_attachment = false
      health_check = {
        path = "/"
      }
    }
  }

  tags = local.tags
}

module "app" {
  source = "./modules/ecs-service"

  name                  = "${local.name}-app"
  cluster_name          = local.name
  region                = var.region
  vpc_id                = module.vpc.vpc_id
  subnet_ids            = module.vpc.private_subnets
  alb_security_group_id = module.alb.security_group_id
  target_group_arn      = module.alb.target_groups["app"].arn
  image                 = var.app_image
  container_port        = var.app_port

  # モジュールの出力 → ローカルモジュールの変数 → タスク定義の環境変数、と境界を2つ越える参照（確定の辺の根拠）
  environment = {
    DB_HOST = module.db.db_instance_address
    DB_NAME = "app"
  }

  # サービスはリスナーが付いたターゲットグループにしか登録できない（three-tier の depends_on = [aws_lb_listener.http] に当たる）
  depends_on = [module.alb]
}

# DB の SG はルートに置く（module.app と module.db の両方が参照する）
resource "aws_security_group" "db" {
  name        = "${local.name}-db"
  description = "RDS"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description     = "PostgreSQL from app"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [module.app.security_group_id]
  }
}

module "db" {
  source  = "terraform-aws-modules/rds/aws"
  version = "~> 7.0" # v7 は aws provider >= 6.28・Terraform >= 1.11.1（vpc ~> 6.7・alb ~> 10.0 と同じ provider の系列）

  identifier           = "${local.name}-db"
  engine               = "postgres"
  engine_version       = "17.9"
  family               = "postgres17"
  major_engine_version = "17"
  instance_class       = "db.t4g.micro"
  allocated_storage    = 20
  storage_encrypted    = true

  db_name                     = "app"
  username                    = "app_admin"
  port                        = "5432" # rds モジュールの port は string 型
  manage_master_user_password = true
  multi_az                    = false

  db_subnet_group_name   = module.vpc.database_subnet_group_name
  vpc_security_group_ids = [aws_security_group.db.id]

  # 要約表で展開するリソースを確定させるため、作られるかどうかが既定値で変わるものは明示する
  create_db_subnet_group    = false
  create_db_parameter_group = false
  create_db_option_group    = false
  create_monitoring_role    = false
  skip_final_snapshot       = true
  deletion_protection       = false

  tags = local.tags
}
