import {
  ArrowRight,
  Mail,
  Moon,
  Sparkles,
} from "lucide-react";

import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import "./Login.css";


declare global {
  interface Window {
    onTelegramAuth: (user: unknown) => void;
  }
}


const Login = () => {
  const navigate = useNavigate();


  useEffect(() => {

    window.onTelegramAuth = async (user) => {

      console.log(
        "Usuário Telegram:",
        user
      );


      try {

        await fetch(
          "http://localhost:8000/telegram/auth",
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify(user),
          }
        );


        navigate("/dashboard");


      } catch (error) {

        console.error(
          "Erro no login Telegram:",
          error
        );

      }

    };


    const script = document.createElement(
      "script"
    );


    script.src =
      "https://telegram.org/js/telegram-widget.js?22";


    script.async = true;


    script.setAttribute(
      "data-telegram-login",
      "dominandoanimacao_bot"
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


    const container =
      document.getElementById(
        "telegram-login"
      );


    if (container) {

      container.innerHTML = "";

      container.appendChild(
        script
      );

    }


    return () => {

      if (container) {
        container.innerHTML = "";
      }

    };


  }, [navigate]);



  return (
    <main className="login-page">

      <div
        className="login-background"
        aria-hidden="true"
      >
        <span className="login-background__glow login-background__glow--top" />
        <span className="login-background__glow login-background__glow--center" />
        <span className="login-background__grid" />
      </div>



      <button
        className="login-theme-button"
        type="button"
        aria-label="Alternar tema"
      >
        <Moon
          size={19}
          strokeWidth={1.8}
        />
      </button>



      <section className="login-content">


        <header className="login-brand">

          <div
            className="login-brand__logo"
            aria-hidden="true"
          >
            <Sparkles
              size={34}
              strokeWidth={2.1}
            />
          </div>


          <h1 className="login-brand__title">
            <span>
              Dominando
            </span>

            <strong>
              Animação
            </strong>
          </h1>


          <p className="login-brand__description">
            Estúdio de geração de mídia com IA
          </p>

        </header>




        <section
          className="login-card"
          aria-labelledby="login-title"
        >

          <div
            className="login-card__shine"
            aria-hidden="true"
          />



          <h2
            id="login-title"
            className="login-card__title"
          >
            Acesse sua conta
          </h2>



          <p className="login-card__description">
            Entre com o Telegram ou receba um código pelo seu e-mail.
          </p>



          <div
            id="telegram-login"
            className="login-telegram-button"
          />




          <div className="login-divider">

            <span className="login-divider__line" />

            <span className="login-divider__text">
              OU
            </span>

            <span className="login-divider__line" />

          </div>





          <form
            className="login-form"
            onSubmit={(event) => {

              event.preventDefault();

              navigate("/dashboard");

            }}
          >


            <div className="login-form__group">

              <label
                className="login-form__label"
                htmlFor="email"
              >
                Entrar com e-mail
              </label>



              <div className="login-form__input-wrapper">


                <Mail
                  className="login-form__input-icon"
                  size={19}
                  strokeWidth={1.9}
                />



                <input
                  className="login-form__input"
                  id="email"
                  name="email"
                  type="email"
                  placeholder="seu@email.com"
                  autoComplete="email"
                  required
                />

              </div>

            </div>




            <button
              className="login-submit-button"
              type="submit"
            >

              <span>
                Enviar código
              </span>


              <ArrowRight
                size={19}
                strokeWidth={2}
              />

            </button>


          </form>




          <p className="login-card__notice">
            Acesso liberado apenas para assinantes com plano ativo.
          </p>


        </section>




        <footer className="login-footer">

          <span>
            Acesso restrito
          </span>


          <span className="login-footer__separator">
            •
          </span>


          <span>
            Dominando Animação
          </span>


        </footer>



      </section>


    </main>
  );
};


export default Login;