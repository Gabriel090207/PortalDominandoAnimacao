import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

const TelegramCallback = () => {

  const navigate = useNavigate();

  useEffect(() => {

    navigate("/dashboard");

  }, [navigate]);


  return (
    <div>
      Entrando com Telegram...
    </div>
  );
};


export default TelegramCallback;