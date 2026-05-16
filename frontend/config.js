// API configuration
// Optional global override:
//   window.__IXSE_API_BASE_URL = "https://api.example.com";
// If not set, default to the same host serving the UI, but backend port 8080.
const API_BASE_URL =
  window.__IXSE_API_BASE_URL ||
  `${window.location.protocol}//${window.location.hostname}:8080`;
