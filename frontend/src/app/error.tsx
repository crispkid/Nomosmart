"use client";

import { RecoveryScreen } from "@/components/RecoveryScreen";
import { useRouter } from "next/navigation";
import { startTransition } from "react";

export default function ErrorPage({ reset }: { reset: () => void }) {
  const router = useRouter();
  function retry() {
    startTransition(() => {
      router.refresh();
      reset();
    });
  }
  return <RecoveryScreen kind="region" onRetry={retry} />;
}
