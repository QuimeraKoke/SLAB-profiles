"use client";

import { useState, useEffect } from "react";
import Image from "next/image";
import { useAuth } from "@/context/AuthContext";
import styles from "./page.module.css";

const VIDEO_PLAYLIST = [
  "/videos/soccer-cherring.mp4",
  "/videos/soccer-warm.mp4"
];

export default function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [bgVideo, setBgVideo] = useState<string | null>(null);

  useEffect(() => {
    // Pick a random video on the client to prevent hydration mismatch
    const randomIdx = Math.floor(Math.random() * VIDEO_PLAYLIST.length);
    setBgVideo(VIDEO_PLAYLIST[randomIdx]);
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (email) {
      login(email);
    }
  };

  return (
    <main className={styles.container}>
      {/* Background Video */}
      {bgVideo && (
        <video
          key={bgVideo}
          src={bgVideo}
          autoPlay
          loop
          muted
          playsInline
          className={styles.videoBg}
        />
      )}
      <div className={styles.videoOverlay} />

      {/* Login Form */}
      <div className={styles.loginBox}>
        <div className={styles.logoContainer}>
          <Image
            src="/slab-logo.svg"
            alt="SLAB Logo"
            width={100}
            height={71}
            className={styles.logoImage}
            priority
          />
          <h1 className={styles.logoText}>SLAB</h1>
        </div>

        <form className={styles.form} onSubmit={handleSubmit}>
          <div className={styles.inputGroup}>
            <label htmlFor="email" className={styles.label}>Email</label>
            <input
              id="email"
              type="email"
              className={styles.input}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="ronal@dinho.com"
              required
            />
          </div>

          <div className={styles.inputGroup}>
            <label htmlFor="password" className={styles.label}>Password</label>
            <input
              id="password"
              type="password"
              className={styles.input}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={"•".repeat(15)}
              required
            />
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <label className={styles.checkboxGroup}>
              <input type="checkbox" className={styles.checkbox} defaultChecked />
              Keep me logged in
            </label>

            <button type="submit" className={styles.submitButton}>
              Login
            </button>
          </div>
        </form>
      </div>
    </main>
  );
}
