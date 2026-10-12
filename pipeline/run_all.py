from pipeline import load_dimensions, load_hours, quality_check, report


def main():
    for step in (load_dimensions, load_hours, quality_check, report):
        print(f"\n===== {step.__name__.split('.')[-1]} =====")
        step.main()


if __name__ == "__main__":
    main()