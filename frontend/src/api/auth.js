import apiClient from "./client";

export async function loginUser(email, password) {
  const { data } = await apiClient.post("/auth/login", { email, password });
  return data;
}

export async function registerUser(email, full_name, password) {
  const { data } = await apiClient.post("/auth/register", { email, full_name, password });
  return data;
}

export async function refreshTokens(refresh_token) {
  const { data } = await apiClient.post("/auth/refresh", { refresh_token });
  return data;
}

export async function getMe() {
  const { data } = await apiClient.get("/auth/me");
  return data;
}