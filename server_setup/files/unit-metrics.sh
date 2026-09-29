#!/bin/sh
set -u
out=/var/lib/alloy/textfile/units.prom

psi() {
    awk -v metric="$1" '$1 == "full" { split($5, t, "="); printf "%s %.6f\n", metric, t[2] / 1e6 }' "$2"
}

while :; do
    {
        echo "# TYPE systemd_unit_memory_bytes gauge"
        echo "# TYPE systemd_unit_swap_bytes gauge"
        echo "# TYPE systemd_unit_cpu_seconds_total counter"
        echo "# TYPE systemd_unit_memory_stalled_seconds_total counter"
        echo "# TYPE systemd_unit_io_read_bytes_total counter"
        echo "# TYPE systemd_unit_io_written_bytes_total counter"
        echo "# TYPE systemd_unit_io_reads_total counter"
        echo "# TYPE systemd_unit_io_writes_total counter"
        echo "# TYPE systemd_unit_io_stalled_seconds_total counter"
        for dir in /sys/fs/cgroup/system.slice/*.service /sys/fs/cgroup/system.slice/*.slice/*.service; do
            [ -d "$dir" ] || continue
            label="{unit=\"$(printf %s "${dir##*/}" | sed 's/\\/\\\\/g')\"}"
            [ -r "$dir/memory.current" ] && echo "systemd_unit_memory_bytes$label $(cat "$dir/memory.current")"
            [ -r "$dir/memory.swap.current" ] && echo "systemd_unit_swap_bytes$label $(cat "$dir/memory.swap.current")"
            [ -r "$dir/cpu.stat" ] && awk -v l="$label" '$1 == "usage_usec" { printf "systemd_unit_cpu_seconds_total%s %.6f\n", l, $2 / 1e6 }' "$dir/cpu.stat"
            [ -r "$dir/memory.pressure" ] && psi "systemd_unit_memory_stalled_seconds_total$label" "$dir/memory.pressure"
            [ -r "$dir/io.stat" ] && awk -v l="$label" '
                { for (i = 2; i <= NF; i++) { split($i, kv, "="); sum[kv[1]] += kv[2] } }
                END {
                    printf "systemd_unit_io_read_bytes_total%s %.0f\n", l, sum["rbytes"]
                    printf "systemd_unit_io_written_bytes_total%s %.0f\n", l, sum["wbytes"]
                    printf "systemd_unit_io_reads_total%s %.0f\n", l, sum["rios"]
                    printf "systemd_unit_io_writes_total%s %.0f\n", l, sum["wios"]
                }' "$dir/io.stat"
            [ -r "$dir/io.pressure" ] && psi "systemd_unit_io_stalled_seconds_total$label" "$dir/io.pressure"
        done
    } > "$out.tmp"
    mv "$out.tmp" "$out"
    sleep 30
done
