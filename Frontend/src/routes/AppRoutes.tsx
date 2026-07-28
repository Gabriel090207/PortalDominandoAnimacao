import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
} from "react-router-dom";

import MainLayout from "../layouts/MainLayout";

import Login from "../pages/Login/Login";
import TelegramCallback from "../pages/TelegramCallback/TelegramCallback";

import Dashboard from "../pages/Dashboard/Dashboard";
import Video from "../pages/Video/Video";
import Voice from "../pages/Voice/Voice";
import Image from "../pages/Image/Image";
import Chat from "../pages/Chat/Chat";
import Slides from "../pages/Slides/Slides";
import Library from "../pages/Library/Library";


const AppRoutes = () => {
  return (
    <BrowserRouter>

      <Routes>

        {/* Login */}
        <Route
          path="/"
          element={<Login />}
        />


        {/* Retorno Telegram */}
        <Route
          path="/telegram/callback"
          element={<TelegramCallback />}
        />


        {/* Área interna */}
        <Route element={<MainLayout />}>

          <Route
            path="/dashboard"
            element={<Dashboard />}
          />

          <Route
            path="/video"
            element={<Video />}
          />

          <Route
            path="/voice"
            element={<Voice />}
          />

          <Route
            path="/image"
            element={<Image />}
          />

          <Route
            path="/chat"
            element={<Chat />}
          />

          <Route
            path="/slides"
            element={<Slides />}
          />

          <Route
            path="/library"
            element={<Library />}
          />

        </Route>


        {/* Qualquer rota inválida */}
        <Route
          path="*"
          element={
            <Navigate
              to="/"
              replace
            />
          }
        />


      </Routes>

    </BrowserRouter>
  );
};


export default AppRoutes;