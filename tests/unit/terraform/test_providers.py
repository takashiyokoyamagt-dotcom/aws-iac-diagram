"""Terraform アダプタ: provider の alias とリージョン。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import assert_valid, res_of
from support.terraform import build, codes


class ProviderTest(unittest.TestCase):
    def test_provider_alias_and_region(self):
        raw = build("""
        provider "aws" {
          region = var.region
        }
        provider "aws" {
          alias  = "us_east_1"
          region = "us-east-1"
        }
        provider "aws" {
          alias  = "dr"
          region = var.dr_region
        }
        resource "aws_acm_certificate" "cert" {
          provider    = aws.us_east_1
          domain_name = "example.com"
        }
        resource "aws_s3_bucket" "dr" {
          provider = aws.dr
        }
        resource "aws_s3_bucket" "main" {
          provider = aws
        }
        resource "aws_s3_bucket" "lost" {
          provider = aws.nowhere
        }
        """)
        assert_valid(self, raw)
        cert = res_of(raw, "aws_acm_certificate.cert")
        self.assertEqual((cert["provider"], cert["region"]), ("aws.us_east_1", "us-east-1"))
        self.assertNotIn("provider", cert["props"])
        dr = res_of(raw, "aws_s3_bucket.dr")
        self.assertEqual(dr["provider"], "aws.dr")
        self.assertNotIn("region", dr)  # region が決まらない（手順2）
        self.assertNotIn("provider", res_of(raw, "aws_s3_bucket.main"))  # 既定の provider は書かない
        self.assertIn("TF-PROVIDER-UNCONFIGURED", codes(raw, "aws_s3_bucket.lost"))

    def test_resource_region_argument_and_quoted_provider(self):
        raw = build("""
        provider "aws" {
          alias  = "w"
          region = "us-west-2"
        }
        resource "aws_s3_bucket" "regional" {
          region = "eu-west-1"
        }
        resource "aws_s3_bucket" "both" {
          provider = aws.w
          region   = "eu-west-1"
        }
        resource "aws_s3_bucket" "quoted" {
          provider = "aws.w"
        }
        resource "random_id" "x" {
          region = "not-a-region"
        }
        """)
        assert_valid(self, raw)
        # リソースの引数 region（AWS provider v6）は provider の region より優先する（Terraform と同じ）
        regional = res_of(raw, "aws_s3_bucket.regional")
        self.assertEqual((regional.get("provider"), regional["region"]), (None, "eu-west-1"))
        self.assertEqual(regional["props"]["region"], "eu-west-1")
        both = res_of(raw, "aws_s3_bucket.both")
        self.assertEqual((both["provider"], both["region"]), ("aws.w", "eu-west-1"))
        quoted = res_of(raw, "aws_s3_bucket.quoted")  # 古い書き方の文字列も読む
        self.assertEqual((quoted["provider"], quoted["region"]), ("aws.w", "us-west-2"))
        self.assertNotIn("region", res_of(raw, "random_id.x"))  # AWS の型だけ


if __name__ == "__main__":
    unittest.main()
