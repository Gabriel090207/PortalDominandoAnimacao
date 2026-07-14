import {
  Bell,
  ChevronDown,
  Clock3,
  MessageSquarePlus,
  Paperclip,
  Send,
  Sparkles,
} from "lucide-react";

import Sidebar from "../../components/Sidebar/Sidebar";

import "./Chat.css";

const Chat = () => {
  return (
    <>
      <Sidebar />

      <main className="chat-page">

        <header className="chat-topbar">

          <div className="chat-model">

            <div className="chat-model__logo">
              <Sparkles size={18} />
            </div>

            <span>ChatGPT 5.5</span>

            <ChevronDown size={18} />

          </div>

          <div className="chat-topbar__actions">

            <button
              className="chat-history"
              type="button"
            >
              <Clock3 size={18} />
            </button>

            <button
              className="chat-new"
              type="button"
            >
              <MessageSquarePlus size={18} />

              <span>Nova</span>
            </button>

            <button
              className="chat-status"
              type="button"
            />

            <button
              className="chat-notification"
              type="button"
            >
              <Bell size={18} />
            </button>

          </div>

        </header>

        <section className="chat-welcome">

          <div className="chat-welcome__logo">

            <Sparkles size={42} />

          </div>

          <h1>
            Como posso ajudar?
          </h1>

          <p>
            Conversando com ChatGPT 5.5
          </p>

        </section>

        <section className="chat-suggestions">

          <button>

            <Sparkles size={16} />

            <span>
              Explique um assunto complexo de forma simples
            </span>

          </button>

          <button>

            <Sparkles size={16} />

            <span>
              Revise este código e aponte melhorias
            </span>

          </button>

          <button>

            <Sparkles size={16} />

            <span>
              Resuma um arquivo que eu anexar
            </span>

          </button>

          <button>

            <Sparkles size={16} />

            <span>
              O que tem nesta imagem?
            </span>

          </button>

        </section>

        <footer className="chat-input">

          <button
            className="chat-input__attach"
            type="button"
          >
            <Paperclip size={20} />
          </button>

          <input
            type="text"
            placeholder="Pergunte qualquer coisa..."
          />

          <button
            className="chat-input__send"
            type="button"
          >
            <Send size={18} />
          </button>

        </footer>

        <span className="chat-disclaimer">
          A IA pode cometer erros. Confira informações importantes.
        </span>

      </main>

    </>
  );
};

export default Chat;