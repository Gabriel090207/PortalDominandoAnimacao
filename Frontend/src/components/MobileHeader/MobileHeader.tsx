import { Bell, LogOut, Search, Sparkles } from "lucide-react";

import "./MobileHeader.css";

const MobileHeader = () => {
  return (
    <header className="mobile-header">
      <div className="mobile-header__logo">

  <div className="mobile-header__logo-icon">
    <Sparkles size={18} strokeWidth={2.2} />
  </div>

  <div className="mobile-header__logo-text">
    <span>Dominando</span>
    <strong>Animação</strong>
  </div>

</div>
      <div className="mobile-header__actions">
        <button>
          <Search size={20} />
        </button>

        <button>
          <Bell size={20} />
        </button>

        <div className="mobile-header__avatar">
          GB
        </div>

        <button>
          <LogOut size={20} />
        </button>
      </div>
    </header>
  );
};

export default MobileHeader;