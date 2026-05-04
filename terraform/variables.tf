variable "subscription_id" {
  type      = string
  sensitive = true
}

variable "location" {
  type    = string
  default = "EastUS2"
}

variable "gh_repo" {
  type = string
}


variable "search_knowledge_base_name" {
  type    = string
  default = "knowledgebase-1775762012147"
  
}