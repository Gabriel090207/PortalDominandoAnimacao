import { Outlet } from "react-router-dom";

import Sidebar from "../components/Sidebar/Sidebar";
import MobileHeader from "../components/MobileHeader/MobileHeader";
import BottomNavigation from "../components/BottomNavigation/BottomNavigation";

const MainLayout = () => {
  return (
    <>
      <MobileHeader />

      <Sidebar />

      <main>
        <Outlet />
      </main>

      <BottomNavigation />
    </>
  );
};

export default MainLayout;