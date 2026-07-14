import {
  Bell,
  ChevronDown,
  Clapperboard,
  Clock3,
  MonitorPlay,
  SendHorizontal,
  Video,
} from "lucide-react";

import Sidebar from "../../components/Sidebar/Sidebar";

import "./Video.css";

const VideoPage = () => {
  return (
    <>
      <Sidebar />

      <main className="video-page">

        <header className="video-page__topbar">

          <div className="video-page__actions">

            <button
              className="video-page__status"
              type="button"
            />

            <button
              className="video-page__icon"
              type="button"
            >
              <Bell size={18} />
            </button>

          </div>

        </header>

        <section className="video-page__hero">

          <h1>Vídeo</h1>

          <p>
            Gere clipes a partir de texto e imagens de referência.
          </p>

        </section>

        <section className="video-card">

          <textarea
            placeholder="Descreva a cena que você quer ver em movimento..."
          />

          <div className="video-card__bottom">

            <div className="video-option">

              <span className="video-option__label">
                <Video size={16} />
                Modelo
              </span>

              <button
                className="video-select"
                type="button"
              >
                <span>Selecione</span>

                <ChevronDown size={18} />
              </button>

            </div>

            <div className="video-option">

              <span className="video-option__label">
                <MonitorPlay size={16} />
                Formato
              </span>

              <div className="video-segment">

                <button className="active">
                  16:9
                </button>

                <button>
                  9:16
                </button>

                <button>
                  1:1
                </button>

              </div>

            </div>

            <div className="video-option">

              <span className="video-option__label">
                <MonitorPlay size={16} />
                Resolução
              </span>

              <div className="video-segment">

                <button>
                  480p
                </button>

                <button className="active">
                  720p
                </button>

                <button>
                  1080p
                </button>

              </div>

            </div>

            <div className="video-option">

              <span className="video-option__label">
                <Clock3 size={16} />
                Duração
              </span>

              <div className="video-segment">

                <button className="active">
                  6s
                </button>

                <button>
                  10s
                </button>

              </div>

            </div>

            <button
              className="video-generate"
              type="button"
            >
              <SendHorizontal size={18} />

              <span>Gerar</span>

            </button>

          </div>

        </section>

        <section className="video-empty">

          <div className="video-empty__icon">

            <Clapperboard size={34} />

          </div>

          <h2>
            Nenhum vídeo ainda
          </h2>

          <p>
            Descreva uma cena acima e clique em Gerar.
          </p>

        </section>

      </main>

    </>
  );
};

export default VideoPage;