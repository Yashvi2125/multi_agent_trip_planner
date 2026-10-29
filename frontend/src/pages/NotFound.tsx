import { Link } from "react-router-dom";
import { Button, EmptyState } from "@/components/ui";

export default function NotFound() {
  return <main className="mx-auto max-w-6xl px-4 py-16"><EmptyState title="This page took a wrong turn" action={<Link to="/"><Button>Back to the start</Button></Link>}>We couldn't find what you were looking for.</EmptyState></main>;
}
