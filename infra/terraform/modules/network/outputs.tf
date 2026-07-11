output "network_id" {
  value = google_compute_network.platform.id
}

output "subnet_ids" {
  value = { for region, subnet in google_compute_subnetwork.regional : region => subnet.id }
}
