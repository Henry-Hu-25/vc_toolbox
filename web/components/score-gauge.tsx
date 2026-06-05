"use client";

import { motion, useMotionValue, useTransform, animate } from "framer-motion";
import * as React from "react";
import { tierFromScore, TIER_META } from "@/lib/tier";

interface Props {
  score: number;
  size?: number;
  strokeWidth?: number;
}

export function ScoreGauge({ score, size = 160, strokeWidth = 12 }: Props) {
  const clamped = Math.max(0, Math.min(100, score));
  const tier = tierFromScore(clamped);
  const color = `hsl(${TIER_META[tier].color})`;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;

  const mv = useMotionValue(0);
  const offset = useTransform(mv, (v) => circumference - (circumference * v) / 100);
  const rounded = useTransform(mv, (v) => Math.round(v));

  React.useEffect(() => {
    const controls = animate(mv, clamped, {
      duration: 1.1,
      ease: [0.2, 0.8, 0.2, 1],
    });
    return () => controls.stop();
  }, [clamped, mv]);

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="hsl(var(--border))"
          strokeWidth={strokeWidth}
          fill="none"
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={color}
          strokeWidth={strokeWidth}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={circumference}
          style={{ strokeDashoffset: offset, rotate: -90, transformOrigin: "center" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <motion.span
          className="text-4xl font-semibold tabular-nums"
          style={{ color }}
        >
          {rounded}
        </motion.span>
        <span className="text-xs text-muted-fg mt-1">out of 100</span>
      </div>
    </div>
  );
}
