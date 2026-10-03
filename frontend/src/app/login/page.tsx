import { cookies } from "next/headers";
import LoginContent from "@/components/LoginContent";
import { AUTH_COOKIES, parseLoginNotice } from "@/lib/authState";

export default async function LoginPage() {
  const cookieStore = await cookies();
  const notice = parseLoginNotice(cookieStore.get(AUTH_COOKIES.loginNotice)?.value);
  const loginChecked = cookieStore.get(AUTH_COOKIES.loginChecked)?.value === "1";
  return <LoginContent notice={notice} loginChecked={loginChecked} />;
}
