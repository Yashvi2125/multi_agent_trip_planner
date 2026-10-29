import { ChatPanel } from "@/components/chat/ChatPanel";

export default function ChatPage() {
  return (
    <div className="h-[calc(100dvh-15rem)] min-h-[420px] overflow-hidden rounded border border-sand">
      <ChatPanel className="h-full" />
    </div>
  );
}
