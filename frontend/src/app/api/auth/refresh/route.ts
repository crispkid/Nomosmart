import { NextResponse } from "next/server";
export async function POST() { return NextResponse.json({ code: "auth_contract_changed", message: "Reload the application to use server sessions" }, { status: 410, headers: { "Cache-Control": "no-store" } }); }
