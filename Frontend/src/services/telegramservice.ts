import api from "./api";

export const getTelegramLogin = async () => {
  const { data } = await api.get("/telegram/login");

  return data;
};

export const verifyTelegramLogin = async (user: unknown) => {
  const { data } = await api.post(
    "/telegram/auth",
    user
  );

  return data;
};