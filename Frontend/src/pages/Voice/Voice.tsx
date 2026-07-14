import {
  Bell,
  Mic,
  ChevronDown,
  Clock3,
  FileText,
  SendHorizontal,
  AudioWaveform,
} from "lucide-react";

import Sidebar from "../../components/Sidebar/Sidebar";

import "./Voice.css";

const Voice = () => {
  return (
    <>
      <Sidebar />

      <main className="voice-page">

        <header className="voice-page__topbar">
          <div className="voice-page__actions">

            <button
              className="voice-page__status"
              type="button"
            />

            <button
              className="voice-page__icon"
              type="button"
            >
              <Bell size={18} />
            </button>

          </div>
        </header>

        <section className="voice-page__hero">

          <h1>Voz</h1>

          <p>
            Transforme texto em narração natural.
          </p>

        </section>

        <div className="voice-tabs">

          <button className="active">
            Narração
          </button>

          <button>
            Diálogo
          </button>

          <button>
            Efeito sonoro
          </button>

          <button>
            Minhas vozes
          </button>

        </div>

        <section className="voice-card">

          <textarea
            placeholder="Escreva o texto que será narrado..."
          />

          <div className="voice-card__bottom">

            <div className="voice-option">

              <span className="voice-option__label">
                <Mic size={16} />
                Voz
              </span>

              <button
                className="voice-select"
                type="button"
              >
                <span>Escolher voz...</span>

                <ChevronDown size={18} />
              </button>

            </div>

            <div className="voice-option">

              <span className="voice-option__label">
                <Clock3 size={16} />
                Velocidade
              </span>

              <div className="voice-segment">

                <button>
                  0.75x
                </button>

                <button className="active">
                  1x
                </button>

                <button>
                  1.25x
                </button>

              </div>

            </div>

            <div className="voice-option">

              <span className="voice-option__label">
                <FileText size={16} />
                Transcrição
              </span>

              <label className="voice-checkbox">

                <input type="checkbox" />

                <span>SRT / JSON</span>

              </label>

            </div>

            <button
              className="voice-generate"
              type="button"
            >
              <SendHorizontal size={18} />

              <span>Narrar</span>

            </button>

          </div>

        </section>

        <section className="voice-empty">

          <div className="voice-empty__icon">

            <AudioWaveform size={34} />

          </div>

          <h2>
            Nenhum áudio ainda
          </h2>

          <p>
            Escreva um texto acima e gere o áudio.
          </p>

        </section>

      </main>
    </>
  );
};

export default Voice;