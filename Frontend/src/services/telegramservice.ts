import api from "./api";


export const getTelegramLogin = async () => {
  const { data } = await api.get("/telegram/login");

  return data;
};