import { useEffect, useRef } from "react";

type TelegramLoginButtonProps = {
  botUsername: string;
  onAuth: (user: unknown) => void;
};

declare global {
  interface Window {
    onTelegramAuth: (user: unknown) => void;
  }
}

const TelegramLoginButton = ({
  botUsername,
  onAuth,
}: TelegramLoginButtonProps) => {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current || !botUsername) {
      return;
    }

    containerRef.current.innerHTML = "";

    window.onTelegramAuth = (user) => {
      onAuth(user);
    };

    const script = document.createElement("script");

    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.async = true;

    script.setAttribute(
      "data-telegram-login",
      botUsername
    );

    script.setAttribute(
      "data-size",
      "large"
    );

    script.setAttribute(
      "data-userpic",
      "false"
    );

    script.setAttribute(
      "data-request-access",
      "write"
    );

    script.setAttribute(
      "data-onauth",
      "onTelegramAuth(user)"
    );

    containerRef.current.appendChild(script);

    return () => {
      if (containerRef.current) {
        containerRef.current.innerHTML = "";
      }
    };
  }, [botUsername, onAuth]);

  return (
    <div ref={containerRef} />
  );
};

export default TelegramLoginButton;