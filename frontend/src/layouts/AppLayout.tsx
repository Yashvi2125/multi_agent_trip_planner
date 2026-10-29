import { Compass, LogOut } from "lucide-react";
import { Link, Outlet, useNavigate } from "react-router-dom";
import { Avatar, Button } from "@/components/ui";
import { useAuth } from "@/store/auth";

export function Logo({ to = "/" }: { to?: string }) {
  return (
    <Link to={to} className="flex items-center gap-2 font-display text-[22px] font-semibold tracking-tight">
      <span aria-hidden className="grid size-7 place-items-center rounded bg-lagoon text-paper"><Compass size={17} /></span>Wayfare
    </Link>
  );
}

export function AppLayout() {
  const { user, status, logout } = useAuth();
  const nav = useNavigate();
  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-40 border-b border-sand bg-paper/95 backdrop-blur-sm" style={{ paddingTop: "env(safe-area-inset-top)" }}>
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-4">
          <Logo to={user ? "/trips" : "/"} />
          <div className="flex-1" />
          {status === "authed" && user ? (
            <>
              <Link to="/trips" className="hidden text-sm font-semibold text-ink-soft hover:text-ink sm:block">My trips</Link>
              <Link to="/join" className="hidden text-sm font-semibold text-ink-soft hover:text-ink sm:block">Join</Link>
              <span className="flex items-center gap-2 text-sm"><Avatar name={user.name} id={user.id} size={28} /><span className="hidden font-semibold md:inline">{user.name}</span></span>
              <button onClick={async () => { await logout(); nav("/"); }} aria-label="Sign out" className="rounded p-2 text-ink-soft hover:bg-sand-light"><LogOut size={17} /></button>
            </>
          ) : status === "anon" ? (
            <>
              <Link to="/login" className="text-sm font-semibold text-ink-soft hover:text-ink">Sign in</Link>
              <Link to="/register"><Button variant="primary" size="sm">Get started</Button></Link>
            </>
          ) : null}
        </div>
      </header>
      <Outlet />
    </div>
  );
}
