import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import "../styles/pekka.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata = {
  title: "PEKKA — Voice Pill Interface",
  description: "Animated PEKKA-inspired voice assistant interface",
};

export default function RootLayout({ children }) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full bg-transparent antialiased`}
    >
      <body className="h-full min-h-full bg-transparent">{children}</body>
    </html>
  );
}
