import {
  Bell,
  Boxes,
  ChevronDown,
  FileImage,
  ImageIcon,
  SendHorizontal,
} from "lucide-react";

import Sidebar from "../../components/Sidebar/Sidebar";

import "./Image.css";

const Image = () => {
  return (
    <>
      <Sidebar />

      <main className="image-page">

        <header className="image-page__topbar">

          <div className="image-page__actions">

            <button
              className="image-page__status"
              type="button"
            />

            <button
              className="image-page__icon"
              type="button"
            >
              <Bell size={18} />
            </button>

          </div>

        </header>

        <section className="image-page__hero">

          <h1>Imagem</h1>

          <p>
            Crie imagens a partir de uma descrição.
          </p>

        </section>

        <section className="image-card">

          <textarea
            placeholder="Descreva a imagem que você imagina..."
          />

          <div className="image-card__bottom">

            <div className="image-option">

              <span className="image-option__label">

                <Boxes size={16} />

                Modelo

              </span>

              <button
                className="image-select"
                type="button"
              >

                <div className="image-model">

                  <div className="image-model__logo">
                    F
                  </div>

                  <span>
                    FLUX 1.1 Pro
                  </span>

                  <small>
                    Estável
                  </small>

                </div>

                <ChevronDown size={18} />

              </button>

            </div>

            <div className="image-option">

              <span className="image-option__label">

                <FileImage size={16} />

                Formato

              </span>

              <div className="image-segment">

                <button className="active">
                  1:1
                </button>

                <button>
                  16:9
                </button>

                <button>
                  9:16
                </button>

                <button>
                  3:2
                </button>

              </div>

            </div>

            <button
              className="image-generate"
              type="button"
            >

              <SendHorizontal size={18} />

              <span>Gerar</span>

            </button>

          </div>

        </section>

        <section className="image-empty">

          <div className="image-empty__icon">

            <ImageIcon size={34} />

          </div>

          <h2>
            Nenhuma imagem ainda
          </h2>

          <p>
            Descreva uma cena acima e clique em Gerar.
          </p>

        </section>

      </main>

    </>
  );
};

export default Image;