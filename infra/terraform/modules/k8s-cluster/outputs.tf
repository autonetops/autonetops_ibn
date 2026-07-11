output "cluster_name" {
  value = google_container_cluster.platform.name
}

output "cluster_endpoint" {
  value     = google_container_cluster.platform.endpoint
  sensitive = true
}
