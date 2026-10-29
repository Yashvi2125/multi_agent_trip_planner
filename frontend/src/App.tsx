import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppLayout } from "@/layouts/AppLayout";
import TripLayout from "@/layouts/TripLayout";
import BudgetPage from "@/pages/BudgetPage";
import ChatPage from "@/pages/ChatPage";
import CreateTrip from "@/pages/CreateTrip";
import ItineraryPage from "@/pages/ItineraryPage";
import JoinTrip from "@/pages/JoinTrip";
import Landing from "@/pages/Landing";
import { Login, Register } from "@/pages/AuthPages";
import MembersPage from "@/pages/MembersPage";
import NotFound from "@/pages/NotFound";
import Overview from "@/pages/Overview";
import SettingsPage from "@/pages/SettingsPage";
import Trips from "@/pages/Trips";
import { useAuth } from "@/store/auth";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { status } = useAuth();
  const loc = useLocation();
  if (status === "loading") return <div className="grid min-h-[50vh] place-items-center text-ink-soft"><span className="dots">Loading</span></div>;
  if (status === "anon") return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Landing />} />
        <Route path="login" element={<Login />} />
        <Route path="register" element={<Register />} />
        <Route path="trips" element={<RequireAuth><Trips /></RequireAuth>} />
        <Route path="create" element={<RequireAuth><CreateTrip /></RequireAuth>} />
        <Route path="join" element={<RequireAuth><JoinTrip /></RequireAuth>} />
        <Route path="join/:code" element={<RequireAuth><JoinTrip /></RequireAuth>} />
        <Route path="trip/:tripId" element={<RequireAuth><TripLayout /></RequireAuth>}>
          <Route index element={<Overview />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="itinerary" element={<ItineraryPage />} />
          <Route path="budget" element={<BudgetPage />} />
          <Route path="members" element={<MembersPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
