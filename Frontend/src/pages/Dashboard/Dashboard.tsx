import {
  Bell,
  BookOpen,
  Bot,
  FileImage,
  Search,
  Video,
  Volume2,
} from "lucide-react";

import Sidebar from "../../components/Sidebar/Sidebar";

import "./Dashboard.css";

const Dashboard = () => {
  return (
    <>



      <Sidebar />

   

      <main className="dashboard">

        <header className="dashboard__topbar">

          <div className="dashboard__topbar-actions">

            <button
              className="dashboard__topbar-button dashboard__topbar-button--status"
              type="button"
            />

            <button
              className="dashboard__topbar-button"
              type="button"
            >
              <Bell size={18} />
            </button>

          </div>

        </header>

        <section className="dashboard__hero">

          <span className="dashboard__eyebrow">
            ESTÚDIO • DOMINANDO ANIMAÇÃO
          </span>

          <h1 className="dashboard__title">
            Boa noite, <span>Gabriel.</span>
          </h1>

          <p className="dashboard__subtitle">
            O que você quer criar hoje?
          </p>

        </section>

        <section className="dashboard__search">

          <Search
            className="dashboard__search-icon"
            size={20}
          />

          <input
            type="text"
            placeholder="Pergunte ou navegue..."
          />

        </section>

        <section className="dashboard__grid">

          <article className="dashboard-card">

            <div className="dashboard-card__icon">
              <Video size={24} />
            </div>

            <div>
              <h3>Vídeo</h3>
              <p>Texto e imagem em vídeo</p>
            </div>

          </article>

          <article className="dashboard-card">

            <div className="dashboard-card__icon">
              <Volume2 size={24} />
            </div>

            <div>
              <h3>Voz</h3>
              <p>Texto em voz natural</p>
            </div>

          </article>

          <article className="dashboard-card">

            <div className="dashboard-card__icon">
              <FileImage size={24} />
            </div>

            <div>
              <h3>Imagem</h3>
              <p>Texto em imagem</p>
            </div>

          </article>

          <article className="dashboard-card">

            <div className="dashboard-card__icon">
              <Bot size={24} />
            </div>

            <div>
              <h3>Chat IA</h3>
              <p>Geração e edição de texto</p>
            </div>

          </article>

          <article className="dashboard-card">

            <div className="dashboard-card__icon">
              <BookOpen size={24} />
            </div>

            <div>
              <h3>Slides</h3>
              <p>Apresentações prontas</p>
            </div>

          </article>

          <article className="dashboard-card">

            <div className="dashboard-card__icon">
              <BookOpen size={24} />
            </div>

            <div>
              <h3>Biblioteca</h3>
              <p>Tudo que você criou</p>
            </div>

          </article>

        </section>

        <section className="dashboard__recent">

          <div className="dashboard__recent-header">

            <h2>Trabalhos recentes</h2>

            <button type="button">
              Ver tudo
            </button>

          </div>

          <div className="dashboard__empty">

            <div className="dashboard__empty-icon">
              <BookOpen size={28} />
            </div>

            <h3>Nada por aqui ainda</h3>

            <p>
              Escolha uma ferramenta acima e comece a criar.
            </p>

          </div>

        </section>

      </main>
    </>
  );
};

export default Dashboard;