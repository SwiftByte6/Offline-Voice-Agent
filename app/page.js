"use client";

import { useSyncExternalStore } from "react";
import PekkaVoicePill from "@/components/pekka/PekkaVoicePill";
import { isTauriRuntime } from "@/lib/tauriWindow";

const emptySubscribe = () => () => {};

function useIsTauri() {
  return useSyncExternalStore(
    emptySubscribe,
    () => isTauriRuntime(),
    () => false
  );
}

export default function Home() {
  const inTauri = useIsTauri();

  return (
    <main
      className={`flex h-screen w-screen items-center justify-center ${
        inTauri ? "bg-transparent" : "bg-[#18181b]"
      }`}
    >
      <PekkaVoicePill />
    </main>
  );
}
