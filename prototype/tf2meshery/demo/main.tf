terraform {
  required_providers {
    random = { source = "hashicorp/random" }
    local  = { source = "hashicorp/local" }
  }
}
variable "env" { default = "dev" }
resource "random_pet" "name" { prefix = var.env }
resource "random_password" "db" { length = 16 }
resource "local_file" "cfg" {
  for_each = toset(["a", "b"])
  filename = "${path.module}/out-${each.key}.txt"
  content  = "${random_pet.name.id}:${random_password.db.result}"
}
resource "terraform_data" "after" {
  depends_on = [local_file.cfg]
  input      = random_pet.name.id
}
output "pet" { value = random_pet.name.id }
