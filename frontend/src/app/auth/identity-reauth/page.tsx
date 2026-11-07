import { redirect } from "next/navigation";
import { parseIdentityReauthResult } from "@/lib/systemRouteState";

type IdentityReauthPageProps = {
  searchParams: Promise<{ result?: string | string[] }>;
};

export default async function IdentityReauthPage({ searchParams }: IdentityReauthPageProps) {
  const { result } = await searchParams;
  const legacyResult = parseIdentityReauthResult(result);
  const canonicalResult = legacyResult && legacyResult !== "pending" ? legacyResult : "error";
  redirect(`/system?tab=identity&reauth=${canonicalResult}`);
}
