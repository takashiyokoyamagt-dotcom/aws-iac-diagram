# prod だけで作る（count が 0 になるリソースの網羅分類 H-COND-FALSE を試す）

data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_instance" "bastion" {
  count = local.env.enable_bastion ? 1 : 0

  ami                    = data.aws_ssm_parameter.al2023_ami.value
  instance_type          = "t3.micro"
  subnet_id              = aws_subnet.public[0].id
  vpc_security_group_ids = [aws_security_group.bastion[0].id]

  metadata_options {
    http_tokens = "required"
  }

  tags = {
    Name = "${local.name}-bastion"
  }
}
