import pandas as pd


def remove_failed_rows(input_file, output_file):
    try:
        # Read the CSV file
        df = pd.read_csv(input_file)

        original_count = len(df)
        print(f"Loaded {original_count} rows from '{input_file}'.")

        # Filter out rows where 'failed' is True
        # This handles both boolean True and string "True" if parsed correctly
        df_clean = df[df["failed"] == False]

        removed_count = original_count - len(df_clean)
        print(f"Removed {removed_count} rows where failed=True.")
        print(f"Remaining rows: {len(df_clean)}")

        # Save to a new CSV file
        df_clean.to_csv(output_file, index=False)
        print(f"Cleaned data saved to '{output_file}'.")

    except FileNotFoundError:
        print(f"Error: The file '{input_file}' was not found.")
    except KeyError:
        print(
            "Error: The column 'failed' was not found in the CSV. Check the header spelling."
        )
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    input_filename = "greencoding.csv"
    output_filename = "greencoding_new.csv"

    remove_failed_rows(input_filename, output_filename)
