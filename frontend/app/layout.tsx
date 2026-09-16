import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Business Digital Address",
  description: "Official digital communication addresses for registered businesses.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
