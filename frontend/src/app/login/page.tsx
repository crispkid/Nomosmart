import { cookies } from "next/headers";
import LoginContent from "@/components/LoginContent";
import { AUTH_COOKIES, parseLoginNotice } from "@/lib/authState";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ notice?: string }> }) {
  const cookieStore = await cookies();
  const query = await searchParams;
  const notice = parseLoginNotice(query.notice ?? cookieStore.get("nomosmart_login_notice")?.value ?? cookieStore.get(AUTH_COOKIES.loginNotice)?.value);
  const loginChecked = cookieStore.get(AUTH_COOKIES.loginChecked)?.value === "1";
  return <LoginContent notice={notice} loginChecked={loginChecked} />;
}
