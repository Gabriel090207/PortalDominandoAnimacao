import {
  Bell,
  Languages,
  LayoutTemplate,
  Monitor,
  SendHorizontal,
  SlidersHorizontal,
  SquareStack,
  Text,
} from "lucide-react";

import Sidebar from "../../components/Sidebar/Sidebar";

import "./Slides.css";

const Slides = () => {
  return (
    <>
      <Sidebar />

      <main className="slides-page">

        <header className="slides-page__topbar">

          <div className="slides-page__actions">

            <button
              className="slides-page__status"
              type="button"
            />

            <button
              className="slides-page__icon"
              type="button"
            >
              <Bell size={18} />
            </button>

          </div>

        </header>

        <section className="slides-page__hero">

          <h1>Apresentações</h1>

          <p>
            Gere apresentações, documentos e posts profissionais com IA.
          </p>

        </section>

        <section className="slides-card">

          <textarea
            placeholder="Descreva a apresentação que você deseja criar..."
          />

          <div className="slides-options">

            <div className="slides-option">

              <span className="slides-option__label">

                <LayoutTemplate size={16} />

                Formato

              </span>

              <div className="slides-segment">

                <button className="active">
                  Apresentação
                </button>

                <button>
                  Documento
                </button>

                <button>
                  Post Social
                </button>

                <button>
                  Página Web
                </button>

              </div>

            </div>

            <div className="slides-option">

              <span className="slides-option__label">

                <SquareStack size={16} />

                Cartões

              </span>

              <div className="slides-segment">

                <button>5</button>

                <button className="active">
                  10
                </button>

                <button>15</button>

                <button>20</button>

              </div>

            </div>

            <div className="slides-option">

              <span className="slides-option__label">

                <Text size={16} />

                Tamanho do texto

              </span>

              <div className="slides-segment">

                <button>
                  Curto
                </button>

                <button className="active">
                  Médio
                </button>

                <button>
                  Detalhado
                </button>

                <button>
                  Extenso
                </button>

              </div>

            </div>

            <div className="slides-option">

              <span className="slides-option__label">

                <Languages size={16} />

                Idioma

              </span>

              <div className="slides-language">

                <button className="slides-language__selected">
                  🇧🇷 Português (BR)
                </button>

                <button>
                  + Idioma
                </button>

              </div>

            </div>

          </div>

          <div className="slides-footer">

            <button className="slides-advanced">

              <SlidersHorizontal size={17} />

              <span>Opções avançadas</span>

            </button>

            <button
              className="slides-generate"
              type="button"
            >

              <SendHorizontal size={18} />

              <span>Criar</span>

            </button>

          </div>

        </section>

        <section className="slides-empty">

          <div className="slides-empty__icon">

            <Monitor size={34} />

          </div>

          <h2>
            Nenhuma apresentação ainda
          </h2>

          <p>
            Descreva um tema acima e clique em Criar.
          </p>

        </section>

      </main>

    </>
  );
};

export default Slides;