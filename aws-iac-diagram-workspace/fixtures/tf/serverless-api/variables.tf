variable "region" {
  type    = string
  default = "ap-northeast-1"
}

variable "project" {
  type    = string
  default = "shop"
}

# for_each で aws_apigatewayv2_route を作る（キー → ルートキー）
variable "routes" {
  type = map(string)
  default = {
    get_orders  = "GET /orders"
    post_orders = "POST /orders"
  }
}
